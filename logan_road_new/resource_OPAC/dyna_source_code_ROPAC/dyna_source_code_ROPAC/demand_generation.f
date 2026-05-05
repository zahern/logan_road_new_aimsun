      	SUBROUTINE demand_generation(l)
c	! --  
c	! -- This subroutine calculates the number of vehicles generated on
c	! -- each link for each simulation interval.
c	! --
c	! -- This subroutine is called from the loop
c	! -- every simulation interval.
c	! -- This subroutine does not call any other subroutines.
c	! --
c	! -- INPUT: all arrays are transferred via the common blocks.
c	! --
c	! -- OUTPUT:
c	! --   vlg(i) : number of vehicles generated on link i during the current simulation interval.
c	! --
     	use muc_mod
	 integer inumvehgen,error
c --
     	tend=l*tii
     	if(CntDemTime.lt.1) tnext=begint(1)
     	if(CntDemTimeT.lt.1) tnextT=begintT(1)
     	if(CntDemTimeH.lt.1) tnextH=begintH(1)
c --
     	IF(tend.gt.(tnext+0.005))then
	    ztdemGen(:)=0
	    zdem(:,:)=0
	    zfdem(:,:)=0
	    CntDemTime=CntDemTime+1
c --
      	    if(CntDemTime.le.nints)then
	      read(42,*)
       	      DO 223 iz=1,nzones
       	     read(42,*,iostat=error) (zdem(iz,izz),izz=1,nzones)
	      if(error.ne.0)then
	        write(911,*) 'Error when reading demand.dat'
	        Stop
	      endif
c --
223   	      continue
224   	      format(6f10.4)
	      zdem(:,:)=zdem(:,:)*multi
c --
      	      do iz=1,nzones
                 do izz=1,nzones
                   ztdemGen(iz)=ztdemGen(iz)+zdem(iz,izz)
                 enddo
      	      enddo
c --
      	      tnext=begint(CntDemTime+1)
      	      do iz=1,nzones
c        expgenz(iz)=ztdemGen(iz)*multi/((1/tii)*(tnext-begint(CntDemTime)))
         expgenz(iz)=
     + ztdemGen(iz)/((1/tii)*(tnext-begint(CntDemTime)))*Dem_Frac(1)
      	      enddo
c	! --
c	! -- calculate the cumulative probability values for generation
c	! -- of demand towards each zone, in  zfdem(iz,izz,int)
c	! -- Please note the dimension of zfdem and zgdem are different
c	! -- zfdem is the accummulated demand generation prob from zone iz to all zones at time t
c	! -- zgdem is the accummulated demand generation prob	from all zones at time t   
              do iz=1,nzones
               if(ztdemGen(iz).gt.0.0005)then
                zfdem(iz,1)=zdem(iz,1)/ztdemGen(iz)
                do izz=2,nzones
               zfdem(iz,izz)=zfdem(iz,izz-1)+zdem(iz,izz)/ztdemGen(iz)
	        enddo
               else
                zfdem(iz,:)=0.0
               endif
              enddo
            else ! current time is greater than max number of demand duration
              expgenz(:)=0
            endif
	 ENDIF
c --
c --	! -- The folllowing blocks deal with truck demand
c --
	if(Veh_Type(2).eq.1)then
	  if(Dem_Mode(2).eq.1)then ! we have demand_truck.dat
     	    if(nintsT.gt.0)then
     	      IF(tend.gt.(tnextT+0.005))then
      	        ztdemGenT(:)=0.0  
		zdemT(:,:)=0
		CntDemTimeT=CntDemTimeT+1
      		  if(CntDemTimeT.le.nintsT)then
	   	    read(54,*)
       		    DO 2233 iz=1,nzones
c       read(54,2244,iostat=error) (zdemT(iz,izz),izz=1,nzones)
       	read(54,*,iostat=error) (zdemT(iz,izz),izz=1,nzones)
	   		if(error.ne.0)then
        write(911,*) 'Error in gen when reading demand_truck.dat'
	     		stop
	   		endif
2233   		    continue
2244   		    format(6f10.4)
		    zdemT(:,:)=zdemT(:,:)*multiT
		    tnextT=begintT(CntDemTimeT+1)
      		    do iz=1,nzones
         	      do izz=1,nzones
          		ztdemGenT(iz)=ztdemGenT(iz)+zdemT(iz,izz)
         	      enddo
c         expgenzT(iz)=ztdemGenT(iz)*multiT/((1/tii)*(tnextT-begintT(CntDemTimeT)))
       		      expgenzT(iz)=ztdemGenT(iz)/((1/tii)*(tnextT-
     +   	      begintT(CntDemTimeT)))
	  	    enddo
c	! -- Consider total demand (passenger + truck)
c	! -- calculate the cumulative probability values for generation 
c	! -- of demand towards each zone, in  zfdem(iz,izz,int)
c	! -- Please note the dimension of zfdem and zgdem are different
c	! -- zfdem is the accummulated demand generation prob from zone iz to all zones at time t
c	! -- zgdem is the accummulated demand generation prob	from all zones at time t		    
        	    do iz=1,nzones
          		if(ztdemGenT(iz).gt.0.000005)then
            		zfdemT(iz,1)=zdemT(iz,1)/ztdemGenT(iz)
            		  do izz = 2, nzones
       zfdemT(iz,izz)=zfdemT(iz,izz-1)+zdemT(iz,izz)/ztdemGenT(iz)
	        	  enddo
          		else
            		  zfdemT(iz,:)=0.0
          		endif
        	    enddo
        	  else ! current time is greater than max number of demand duration
          	    expgenzT(:)=0
               endif
c -- conbine regular and truck demand
c     expgenz(:)=expgenz(:)+expgenzT(:)
c     ztdemGen(:)=ztdemGen(:)+ztdemGenT(:)
	    ENDIF
     	  Endif
	else ! Dem_Mode(2) = 0
          do iz=1,nzones
             expgenzT(iz)=ztdemGen(iz)/((1/tii)*(tnext-
     +       begint(CntDemTime)))*Dem_Frac(2)
             do izz=1,nzones
                zdemT(iz,izz)=zdem(iz,izz)*Dem_Frac(2)
		zfdemT(iz,izz)=zfdem(iz,izz)
	     enddo
	   enddo
	endif
	endif
c --
c -- The folllowing blocks deal with HOV demand
c --
	if(Veh_Type(3).eq.1)then
	  if(Dem_Mode(3).eq.1)then ! we have demand_HOV.dat
     	    if(nintsH.gt.0)then
     	      IF(tend.gt.(tnextH+0.005))then
      		ztdemGenH(:)=0.0  
		zdemH(:,:)=0
		CntDemTimeH=CntDemTimeH+1
      		  if(CntDemTimeH.le.nintsH)then
	   	    read(61,*)
       		    DO iz=1,nzones
c       read(61,2244,iostat=error) (zdemH(iz,izz),izz=1,nzones)
      	read(61,*,iostat=error) (zdemH(iz,izz),izz=1,nzones)
	   	   if(error.ne.0)then
         write(911,*) 'Error in gen when reading demand_HOV.dat'
	     	     stop
	   	   endif
	   	   enddo
c	2244   format(6f10.4)
		   zdemH(:,:)=zdemH(:,:)*multiH
		   tnextH=begintH(CntDemTimeH+1)
      		   do iz=1,nzones
         	     do izz=1,nzones
          	     ztdemGenH(iz)=ztdemGenH(iz)+zdemH(iz,izz)
         	     enddo
         	     expgenzH(iz)=ztdemGenH(iz)/((1/tii)*(tnextH-
     +   	     begintH(CntDemTimeH)))
	  	   enddo
        	   do iz=1,nzones
          	     if(ztdemGenH(iz).gt.0.000005)then
            	     zfdemH(iz,1)=zdemH(iz,1)/ztdemGenH(iz)
            	     do izz=2,nzones
               		zfdemH(iz,izz)=zfdemH(iz,izz-1)+
     +  		zdemH(iz,izz)/ztdemGenH(iz)
	             enddo
                     else
            		zfdemH(iz,:)=0.0
          	     endif
        	   enddo
        	else ! current time is greater than max number of demand duration
          	   expgenzH(:)=0
        	endif
	      ENDIF
     	    Endif
	  else ! Dem_Mode(3) = 0 
            do iz=1,nzones
              expgenzH(iz)=ztdemGen(iz)/((1/tii)*(tnext-
     +        begint(CntDemTime)))*Dem_Frac(3)
              do izz=1,nzones
                zdemH(iz,izz)=zdem(iz,izz)*Dem_Frac(3)
                zfdemH(iz,izz)=zfdem(iz,izz)
	      enddo
	    enddo
	   endif
	endif
c --
c --	!******************************* PC Vehicles **********************************
	invalidFlag=0
     	do iz=1,nzones  ! for each origin zone
	  if(NoofGenLinksPerZone(iz).eq.0)then
	write(911,*) 'No generation link is found for zone ', iz, 
     +  ', which has positive demand to be generated.'
	    invalidFlag=1
	  endif
	  inumvehgen=0 ! number of vehicles to be generated 
          call DYNA_random_number(r,1)
          if((expgenz(iz)-ifix(expgenz(iz))).gt.r)then
		inumvehgen=ifix(expgenz(iz))+1
          else
		inumvehgen=ifix(expgenz(iz))
	  endif
c     distribution on generation links
	  expgen(:)=0
      	  do il=1,NoofGenLinksPerZone(iz)
            if(LoadWeightID(iz))then
!expgen(LinkNoInZone(iz,il))=expgenz(iz)/TotalLinkLenPerZone(iz)*LoadWeight(LinkNoInZone(iz,il))
		expgen(il)=LoadWeight(LinkNoInZone(iz,il))
	    else
            expgen(il)=original_xl(LinkNoInZone(iz,il))/
     +      TotalLinkLenPerZone(iz)
            endif
	    if(il.gt.1)then
		  expgen(il)=expgen(il)+expgen(il-1)
            endif
	    do izd=1,nzones ! for each destination zone	
	      if(zdem(iz,izd).gt.0.0)then
		if(connectivity(LinkNoInZone(iz,il),MasterDest(izd)).ne.1)then
	write(911,'("link ",i5," -->",i5," is not connected to super 
     + destination",i5," for passenger cars defined in demand.dat")') 
     + nodenum(iunod(LinkNoInZone(iz,il))),
     + nodenum(idnod(LinkNoInZone(iz,il))),izd
		call BacktrackPath(LinkNoInZone(iz,il),MasterDest(izd))
		invalidFlag=1
		endif
	      endif
	    enddo
	  enddo
	  do id=1,inumvehgen
            jj=jj+1 
	    j=jj  ! Determine new veh ID
	    jorigin(j)=iz
	    ioc(j)=1
		  ! Determine vehclass
            call DYNA_random_number(r1,8)
            if(r1.le.MUC_Frac(1,1))then
                vehclass(j)=1
            endif
            do ii=2,nu_classes
       if(r1.le.MUC_Frac(1,ii).and.r1.gt.MUC_Frac(1,ii-1))then
            vehclass(j)=ii
	    exit
       endif
          enddo
	  vehclass2(j)=1 ! PC  without info
          if(vehclass(j).eq.4)then ! the default value for these 3 arrays are 0, given values only if with in-vehicle information (BR)
            info(j)=1
            ribf(j)=ribfa
            compliance(j)=com_frac
	    vehclass2(j)=4 ! PC  with info
          endif
  	Numof_Veh_Type(vehclass2(j))=Numof_Veh_Type(vehclass2(j))+1		  
  	Numof_Veh_Class(vehclass(j))=Numof_Veh_Type(vehclass(j))+1		  
		  ! Determine jdest
          call DYNA_random_number(r5,8)
	  if(j.eq.30)then
	    iiidebug=1
	  endif
	  do izd=1,nzones
	    if(izd.eq.1)then      
		if(r5.le.zfdem(iz,1))then
			jdest(j)=izd
			exit
		endif
	    else
	    if((zdem(iz,izd).gt.0.0).and.(r5.le.zfdem(iz,izd)).and.
     +      (r5.gt.zfdem(iz,izd-1)))then
		jdest(j)=izd
		exit 	
	    endif
	    endif
	  enddo
c		  ! Determine vlg
          call DYNA_random_number(r,1)
c --	print *,'Alex3',NoofGenLinksPerZone(iz),iz
	  do il=1,NoofGenLinksPerZone(iz)
c --	print *,'Alex2',LinkNoInZone(iz,il),iz,il
	    if(il.eq.1)then
	      if(r.le.expgen(1))then
	vlg (LinkNoInZone(iz,il))=vlg(LinkNoInZone(iz,il))+1
	vlg_vhcID(LinkNoInZone(iz,il),vlg(LinkNoInZone(iz,il)))=j
	isec(j)=LinkNoInZone(iz,il)
		exit
	      endif
    	    else	
	      if((r.le.expgen(il)).and.(r.gt.expgen(il-1)))then 
	vlg (LinkNoInZone(iz,il))=vlg(LinkNoInZone(iz,il))+1
	vlg_vhcID(LinkNoInZone(iz,il),vlg(LinkNoInZone(iz,il)))=j
	isec(j)=LinkNoInZone(iz,il)
		exit 	
	      endif
	    endif
	  enddo
	  if(isec(j).eq.0)then
		iiidebug=1 
	  endif
	 enddo	
	enddo
c --
c	!**************************************** End of PC ********************************************
c --
		if(invalidFlag.eq.1) stop
c	!******************************* Truck Vehicles **********************************
	if(Veh_Type(2).eq.1)then  !if we have trucks in network
     	do iz=1,nzones  ! for each origin zone
		inumvehgen=0 ! number of vehicles to be generated 
         call DYNA_random_number(r,1)
           if((expgenzT(iz)-ifix(expgenzT(iz))).gt.r)then
		inumvehgen=ifix(expgenzT(iz))+1
          else
		inumvehgen=ifix(expgenzT(iz))
	 endif
c     	distribution on generation links
		expgen(:)=0
      	do il=1,NoofGenLinksPerZone(iz)
         if(LoadWeightID(iz))then
c		   !expgen(LinkNoInZone(iz,il))=expgenz(iz)/TotalLinkLenPerZone(iz)*LoadWeight(LinkNoInZone(iz,il))
		    expgen(il)=LoadWeight(LinkNoInZone(iz,il))
		 else
	expgen(il)=original_xl(LinkNoInZone(iz,il))/
     +  TotalLinkLenPerZone(iz)
         endif
		if(il.gt.1)then
		  expgen(il)=expgen(il)+expgen(il-1)
          endif
		invalidLinkFoundFlag=0
		    do izd=1,nzones ! for each destination zone
				if(zdemT(iz,izd).gt.0.0)then
	if(connectivity(LinkNoInZone(iz,il),MasterDest(izd)).ne.1)then
	write(911,'("link ",i5," -->",i5," is not connected to super 
     + destination",i5," for trucks defined in demand_truck.dat")') 
     +  nodenum(iunod(LinkNoInZone(iz,il))),
     +  nodenum(idnod(LinkNoInZone(iz,il))),izd
					invalidLinkFoundFlag=1
					endif
				endif
			enddo
			if(invalidLinkFoundFlag.eq.1) stop
      enddo
	      do id=1,inumvehgen
          	jj=jj+1 
		j=jj  ! Determine new veh ID
		jorigin(j)=iz
		ioc(j)=1
		  ! Determine vehclass
          call DYNA_random_number(r1,8)
          if(r1.le.MUC_Frac(2,1))then
                vehclass(j)=1
              endif
              do ii=2,nu_classes
	if(r1.le.MUC_Frac(2,ii).and.r1.gt.MUC_Frac(2,ii-1))then
                  vehclass(j)=ii
	            exit
                endif
              end do
	vehclass2(j)=2 ! Truck  without info
	if(vehclass(j).eq.4) then ! the default value for these 3 arrays are 0, given values only if with in-vehicle information (BR)
                info(j)=1
                 ribf(j)=ribfa
                 compliance(j)=com_frac
	 	vehclass2(j)=5 ! Trcuk  with info
              endif
  	Numof_Veh_Type(vehclass2(j))=Numof_Veh_Type(vehclass2(j))+1		  
  	Numof_Veh_Class(vehclass(j))=Numof_Veh_Type(vehclass(j))+1		  
		  ! Determine jdest
          call DYNA_random_number(r5,8)
		    do izd=1,nzones
			if(izd.eq.1)then      
				if(r5.le.zfdemT(iz,1))then
					jdest(j)=izd
					exit
				endif
			else
	if((zdemT(iz,izd).gt.0.0).and.(r5.le.zfdemT(iz,izd)).and.
     +  (r5.gt.zfdemT(iz,izd-1)))then 
				jdest(j)=izd
					exit 	
				        endif
					endif
			enddo
		  ! Determine vlg
        call DYNA_random_number(r,1)
		do il=1,NoofGenLinksPerZone(iz)
		if(il.eq.1)then      
			if(r.le.expgen(1))then
	vlg(LinkNoInZone(iz,il))=vlg(LinkNoInZone(iz,il))+1
	vlg_vhcID(LinkNoInZone(iz,il),vlg(LinkNoInZone(iz,il)))=j
	isec(j)=LinkNoInZone(iz,il)
			    exit
		     endif
    	else	
	if((r.le.expgen(il)).and.(r.gt.expgen(il-1)))then 
	vlg(LinkNoInZone(iz,il))=vlg(LinkNoInZone(iz,il))+1
	vlg_vhcID(LinkNoInZone(iz,il),vlg(LinkNoInZone(iz,il)))=j
	isec(j)=LinkNoInZone(iz,il)
		exit 	
	endif
		 endif
		enddo
	  enddo	
	 enddo


	endif
c	!**************************************** End of Trucks ********************************************
c	!******************************* HOV Vehicles **********************************
	if(Veh_Type(3).eq.1)then  !if we have trucks in network
     	do iz=1,nzones  ! for each origin zone
		inumvehgen=0 ! number of vehicles to be generated 
         call DYNA_random_number(r,1)
           if((expgenzH(iz)-ifix(expgenzH(iz))).gt.r)then
		inumvehgen=ifix(expgenzH(iz))+1
           else
		inumvehgen=ifix(expgenzH(iz))
	   endif
!     distribution on generation links
		expgen(:)=0
      do il=1,NoofGenLinksPerZone(iz)
        if(LoadWeightID(iz))then
c		   !expgen(LinkNoInZone(iz,il))=expgenz(iz)/TotalLinkLenPerZone(iz)*LoadWeight(LinkNoInZone(iz,il))
		    expgen(il)=LoadWeight(LinkNoInZone(iz,il))
	else
	expgen(il)=original_xl(LinkNoInZone(iz,il))/
     +  TotalLinkLenPerZone(iz)
        endif
	if(il.gt.1)then
		  expgen(il)=expgen(il)+expgen(il-1)
        endif
	invalidLinkFoundFlag=0
	do izd=1,nzones ! for each destination zone
		if(zdemH(iz,izd).gt.0.0)then
	if(connectivity(LinkNoInZone(iz,il),MasterDest(izd)).ne.1)then
	write(911,'("link ",i5," -->",i5," is not connected to super 
     + destination",i5," for HOVs defined in demand_HOV.dat")') 
     +  nodenum(iunod(LinkNoInZone(iz,il))),
     +  nodenum(idnod(LinkNoInZone(iz,il))),izd
	invalidLinkFoundFlag=1
	endif
		endif
	enddo
	if(invalidLinkFoundFlag.eq.1) stop
      enddo
	      do id=1,inumvehgen
          	jj=jj+1 
		j=jj  ! Determine new veh ID
		jorigin(j)=iz
		ioc(j)=2
		  ! Determine vehclass
          call DYNA_random_number(r1,8)
          if(r1.le.MUC_Frac(3,1))then
                vehclass(j)=1
              endif
              do ii=2,nu_classes
         if(r1.le.MUC_Frac(3,ii).and.r1.gt.MUC_Frac(3,ii-1))then
                  vehclass(j)= ii
	            exit
                endif
              enddo
		vehclass2(j)=3 ! HOV  without info
             if(vehclass(j).eq.4)then ! the default value for these 3 arrays are 0, given values only if with in-vehicle information (BR)
                info(j)=1
                ribf(j)=ribfa
                compliance(j)=com_frac
	 	vehclass2(j)=6 ! HOV  with info
              endif
  	Numof_Veh_Type(vehclass2(j))=Numof_Veh_Type(vehclass2(j))+1		  
  	Numof_Veh_Class(vehclass(j))=Numof_Veh_Type(vehclass(j))+1		  
c		  ! Determine jdest
          call DYNA_random_number(r5,8)
		    do izd=1,nzones
			if(izd.eq.1)then      
			if(r5.le.zfdemH(iz,1))then
				jdest(j)=izd
				exit
			endif
			else	
	if((zdemH(iz,izd).gt.0.0).and.(r5.le.zfdemH(iz,izd))
     +  .and.(r5.gt.zfdemH(iz,izd-1)))then 
		jdest(j)=izd
		exit 	
	endif
	endif
	enddo
c		  ! Determine vlg
        call DYNA_random_number(r,1)
		do il=1,NoofGenLinksPerZone(iz)
		if(il.eq.1)then      
			if(r.le.expgen(1))then
	vlg(LinkNoInZone(iz,il))=vlg(LinkNoInZone(iz,il))+1
	vlg_vhcID(LinkNoInZone(iz,il),vlg(LinkNoInZone(iz,il)))=j
	isec(j)=LinkNoInZone(iz,il)
		exit
		     endif
    	 else	
		if((r.le.expgen(il)).and.(r.gt.expgen(il-1)))then 
	vlg(LinkNoInZone(iz,il))=vlg(LinkNoInZone(iz,il))+1
	vlg_vhcID(LinkNoInZone(iz,il),vlg(LinkNoInZone(iz,il)))=j
	isec(j)=LinkNoInZone(iz,il)
		exit 	
		        endif
		 endif
		enddo
	  enddo	
	 enddo
	endif

	return
	end
