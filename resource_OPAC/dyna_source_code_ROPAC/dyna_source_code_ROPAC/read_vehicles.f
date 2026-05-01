      subroutine read_vehicles(t_start)
! --
! --This subroutine reads the vehicle and path files in case the simulation
! --is running through files instead of generating vehicles from OD demand matrix.
! --
! --This subroutine is called from input.
! --This subroutine does not call any other subroutines.
! --
! --INPUT :
! --vehicle.dat : vehicle information file
! --path.dat : vehicle path file
! --
! --OUTPUT :
! --initial vehicle information arrays
! --
      use muc_mod
      use vector_mod
    
	integer Index1D,icn
	real value,t_start
	integer load_veh,error
	integer,save::jtmp,iutmp,idtmp,ndestmp,ntmp,ihovtmp,ivcltmp
	integer,save::infotmp,ivcl2tmp,iorigintemp,jtmp2
	real,save::stimetmp,comptmp,ribftmp
	integer,save::LoadTripChain
    	integer,save::idests_tmp
	integer,save::jpath_tmp(1000)
	integer,save::jpath_tmpInt(1000)
    	integer,save::jdest_tmp(100) 
    	real,save::wait_tmp(10)

    	if(t_start.eq.0.0)then
	jrestore=0
	iread_veh_count=0
      iread_veh_flag=1
	endif

100 	if(iread_veh_count.lt.MaxVehicles)then

   	if(iread_veh_flag.eq.1)then

!     read(500,301)jtmp,iutmp,idtmp,stimetmp,ivcltmp,ivcl2tmp,ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp
!     read(500,*)jtmp,iutmp,idtmp,stimetmp,ivcltmp,ivcl2tmp,ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp,
c	print *,'Alex001'
     	read(500,*)jtmp,iutmp,idtmp,stimetmp,ivcltmp,ivcl2tmp,
     +  ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp,iorigintemp
c     Alex2006: correct vehicle class when loading from vehicle.dat
c	print *, jtmp,iutmp,idtmp,stimetmp,ivcltmp,ivcl2tmp,
c     +  ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp,iorigintemp
	if((MUC_Frac(1,2)-MUC_Frac(1,1)).gt.0.999) ivcltmp=2
	if((MUC_Frac(1,3)-MUC_Frac(1,2)).gt.0.999) ivcltmp=3
	 
      if(jtmp.eq.0) then
	    write(911,*) "Error in vehicle.dat"
	write(911,*) "The number of vehicles listed in this file " 
        write(911,*) "is less than specified at the first line"
		stop
      endif	
	  if(ndestmp.gt.noofstops) then
	    write(911,*) 'error in tripchain.dat'
	    write(911,*) 'the maximum number of stops is exceeded'
	    write(911,*) 'check the vehicle number ', jtmp 
	    stop
      endif
c		print *,'Alex002'
	  do j_ah=1,ndestmp
          read(500,*) jdest_tmp(j_ah),wait_tmp(j_ah)
		  if(j_ah.ge.2) then
            if(jdest_tmp(j_ah).eq.jdest_tmp(j_ah-1)) then
                 print *, 'error in vehicle.dat'
	print *,' found the same dest in consecutive order'
		endif
	 endif
      enddo
 	endif

	if(abs(stimetmp-t_start).gt.0.01) then
          iread_veh_flag=0

	else

        iread_veh_flag = 1
		jrestore = jrestore + 1
		jj= jj+1

        iread_veh_count=iread_veh_count+1
        jm = jrestore
		jorigin(jm)=iorigintemp

        NoOfIntDst(jm) = ndestmp
          do j_ah=1,ndestmp
            IntDestZone(jm,j_ah)=jdest_tmp(j_ah)
            IntDestDwell(jm,j_ah) = wait_tmp(j_ah)
          enddo

          Nlnk=GetFLinkFromNode(idnum(iutmp),idnum(idtmp))

          isec(jm)= Nlnk

          info(jm)=infotmp
		  ribf(jm)=ribftmp
		  compliance(jm)=comptmp
          vehclass(jm)=ivcltmp  !only solve for UE for HOV/HOT vehicle in this version
		  vehclass2(jm)=ivcl2tmp
		  if(ivcl2tmp.eq.2.or.ivcl2tmp.eq.5) then
		    mtnum(jm) = 2.5
          else
			mtnum(jm) = 1
          endif
          stime(jm)=stimetmp
          icurrnt(jm)=1
          xpar(jm)=s(isec(jm))/2
	    DestVisit(jm) = 1
          jdest(jm)=IntDestZone(jm,DestVisit(jm))
	    muc_veh(vehclass(jm))=muc_veh(vehclass(jm))+1


!vehicles for each type
!		  veh_type(vehclass2(jm))= veh_type(vehclass2(jm)) + 1
  	Numof_Veh_Type(vehclass2(jm))=Numof_Veh_Type(vehclass2(jm))+1
  	Numof_Veh_Class(vehclass(jm))=Numof_Veh_Type(vehclass(jm))+1		  

!	      call hot_lane_choice(jm)

!!          if(muc_veh(2).gt.0.and.iso_ok.lt.1) iso_ok = 1
!!	      if(muc_veh(3).gt.0.and.iue_ok.lt.1) iue_ok = 1

		  vlg(isec(jm))=vlg(isec(jm))+1


		  vlg_vhcID(isec(jm),vlg(isec(jm))) = jm



          if(stime(jm).ge.starttm.and.stime(jm).lt.endtm) then
		    itag(jm)=1
	        numcars = numcars + 1
          else
            itag(jm)=0
          endif
          ioc(jm) = ihovtmp
! -- if path is read
          if(realdm.eq.2) then 
		     nnpath(jm) = ntmp
             jpath_tmp(:) = 0
	         read(550,700) mtmp,(jpath_tmp(km),km=1,ntmp-1)
              do Ms = 1, iConZone(idnum(jpath_tmp(ntmp-1)),1)
                if(MasterDest(IntDestZone(jm,ndestmp)).eq.MasterDest
     +  (iConZone(idnum(jpath_tmp(ntmp-1)),Ms+1))) then
                  iflag1 = 1
                  exit
                endif
              enddo
              if(iflag1.lt.1) then 
	write(911,*) 'destination node in path.dat not match vehicle.dat'
			  endif
	         do itmp = 1, ntmp  - 1
                Index1D = itmp
	            value = float(idnum(jpath_tmp(itmp)))
			if(itmp.eq.ntmp-1) then !destination node
			iflag1 = 0
			endif
		    call VhcAtt_Insert(jm,Index1D,1,value)
	         enddo
! -- insert the centroid
        value=float(destination(MasterDest(IntDestZone(jm,ndestmp))))
	         Index1D = ntmp
             call VhcAtt_Insert(jm,Index1D,1,value)
	jpath_tmp(ntmp)=nodenum(destination(MasterDest(
     +  IntDestZone(jm,ndestmp))))

! -- if with incident, check if the vehicle's path contains incidents
! -- check if the vehicle has incident link on its path before diversion
          icn = 0
          
	do Mst = 1, ntmp
	jpath_tmpInt(Mst)=idnum(jpath_tmp(Mst))
	enddo
	call CheckImpact(jpath_tmpInt,jm,icn)



     	  endif
900       continue



		  go to 100

	  endif
  	endif
	
	
200   continue
300   format(4i12,f10.2)
301   format(3i7,f8.2,6i6,2f8.4)
400   format(i12,f7.2)
601   format(5i6,f8.4,i6,2f8.4,2i6)
700   format(280i7)
	  
      return								 
      end


	subroutine CheckImpact (jpath_tmp,jm,icnorg)

	use muc_mod
	use vector_mod
	integer:: jpath_tmp(1000),jm,icnorg,icnt

	      if(inci_num.gt.0.or.WorkZoneNum.gt.0) then
           ImpactType(jm)%InciMode = 0
           ImpactType(Jm)%InciIM = 0
           ImpactType(jm)%WZMode = 0
           ImpactType(Jm)%WZIM = 0
		  endif
	   
	      if(inci_num.gt.0) then
	        do MA = 1, inci_num
              icnt = icnorg
	          jflag = 0
	Nlnk = GetFLinkFromNode((jpath_tmp(icnt+1)),(jpath_tmp(icnt+2)))
             do while(idnod(Nlnk).ne.destination(MasterDest(jdest(jm))))
	             icnt = icnt + 1 
	Nlnk = GetFLinkFromNode((jpath_tmp(icnt+1)),(jpath_tmp(icnt+2)))
                 if(Nlnk.eq.incil(MA)) then ! still on incident link
	                ImpactType(jm)%InciMode = 1
					ImpactType(Jm)%InciIM = MA
					jflag = 1
		            go  to 800
                 endif
	          enddo
	        enddo
	      endif

800  	continue

	      if(WorkZoneNum.gt.0) then

	        do MA = 1, WorkZoneNum
              icnt=icnorg
	          jflag = 0
        NWZLink=GetFLinkFromNode(WorkZone(MA)%FNode,WorkZone(MA)%TNode)
	Nlnk =GetFLinkFromNode((jpath_tmp(icnt+1)),(jpath_tmp(icnt+2)))
            do while(idnod(Nlnk).ne.destination(MasterDest(jdest(jm))))
	             icnt = icnt + 1 
	Nlnk=GetFLinkFromNode((jpath_tmp(icnt+1)),(jpath_tmp(icnt+2)))
		if(Nlnk.eq.NWZLink) then ! still on work zone link
	                ImpactType(jm)%WZMode = 1
				ImpactType(Jm)%WZIM = MA
				jflag = 1
		            go  to 900
                 endif
	          enddo
	        enddo
	      endif

900 	continue



	end subroutine



!**************************************

      subroutine read_vehicles_check_hov()
! --This subroutine reads the vehicle file to check if we have HOV vehicles
! --This subroutine is called from dynasmart
! --This subroutine does not call any other subroutines.
! --
! --INPUT :
! --vehicle.dat : vehicle information file
! --path.dat : vehicle path file
! --
! --OUTPUT :
! --initial vehicle information arrays
! --
    	use muc_mod
	use vector_mod
    
	integer Index1D
	real value
	real t_start
	integer load_veh,error
	integer,save::jtmp,iutmp,idtmp,ndestmp,ntmp,ihovtmp,ivcltmp
	integer,save:: infotmp,jtmp2,ivcl2tmp,jorigintmp
	real,save:: stimetmp,comptmp, ribftmp
	integer,save:: LoadTripChain
    	integer,save:: idests_tmp
	integer,save:: jpath_tmp(1000)
	integer,save:: jpath_tmpInt(1000)
    	integer,save:: jdest_tmp(100)
    	integer icn
    	real,save:: wait_tmp(10)

!	  read(500,*,iostat=error) MaxVehicles, noofstops
!	  read(500,*,iostat=error) !skip a line



  	do iread_veh_count=1,MaxVehicles
!  	do iread_veh_count=0,MaxVehicles

!      read(500,301)jtmp,iutmp,idtmp,stimetmp,ivcltmp,ivcl2tmp,ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp
!      read(500,*,iostat=error)jtmp,iutmp,idtmp,stimetmp,ivcltmp,ivcl2tmp,ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp
c	print *,'Alex003'
       
	 read(500,*,iostat=error)jtmp,iutmp,idtmp,stimetmp,ivcltmp,
     + ivcl2tmp,ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp,jorigintmp

c	 print *, jtmp,iutmp,idtmp,stimetmp,ivcltmp,
c    + ivcl2tmp,ihovtmp,ntmp,ndestmp,infotmp,ribftmp,comptmp,jorigintmp

		if(error.ne.0) then
		write(911,*) 'INPUT ERROR : vehicle.dat data file'
		stop
		endif
c 	print *,'Alex004',ndestmp

	  do j_ah=1,ndestmp
          read(500,*,iostat=error) jdest_tmp(j_ah),wait_tmp(j_ah)
		if(error.ne.0) then
		write(911,*) 'INPUT ERROR : vehicle.dat data file'
		stop
		endif
		  if(j_ah.ge.2) then
            if(jdest_tmp(j_ah).eq.jdest_tmp(j_ah-1)) then
		write(911,*) 'error in vehicle.dat'
		write(911,*)  ' found the same dest in consecutive order'
                 print *, 'error in vehicle.dat'
		print *,' found the same dest in consecutive order'
		stop
		endif
		endif
      	enddo

c 	print *,'Alex005'
! 	
		  if(ihovtmp.eq.2)then
		  no_occupancy_level=2
		  exit
		  endif
	enddo
	
300   format(4i12,f10.2)
301   format(3i7,f8.2,6i6,2f8.4)
400   format(i12,f7.2)
601   format(5i6,f8.4,i6,2f8.4,2i6)
700   format(280i7)

	rewind(500)	  
 	read(500,*,iostat=error) MaxVehicles, noofstops
c 	read(500,*,iostat=error) !skip a line

      return								 
      end
