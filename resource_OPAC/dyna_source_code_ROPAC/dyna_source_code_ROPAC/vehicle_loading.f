      subroutine vehicle_loading(t)     
c	! --
c	! --This subroutine loads the newly generated vehicles into entry queue.
c	! --It then load all t
c	! --
c	! --This subroutine is called from vehicle_simulation
c	! --This subroutine calls the following subroutines
c	! -- 1. bus_generation
c	! -- 2. vehicle_generation
c	! -- 3. get_veh_path
c	! --
c	! --INPUT : 
c	! -- All input is transferred through the common blocks
c	! --
c	! --OUTPUT :
c	! --  updated link information (npar(i), ntryq(i), gen(i), ...).
c	! --
	use muc_mod
	use LinkList_mod
	use vector_mod
c    	use Intooi_mod		!Alex: unnecessary
c --
	type(linkstruct),pointer::pass
	allocate(pass)
c 	print *,'Alex-loading . . .'
c --
	do 7 i=1,noofarcs
c --
	if(link_iden(i).ne.99)then
c --
c	! --
c	! --bus generation subroutine
c	! --    each time interval, check how many buses are generated
c	! --
   	nout(i)=0
   	nmov(i)=0
   	mnum=0.0
c --
c	! Load all the generated vehicles into entry queue
c 	print *,'Alex1',vlg(i)
   	if(vlg(i).gt.0)then
     	   p_mtqj_insert=>EntQueVehList(i)
	   do while(associated(p_mtqj_insert%next_veh)) ! find the end of the list
	      p_mtqj_insert=>p_mtqj_insert%next_veh
	   enddo
c --
c	   print *, 'Alex11120'
     	   do id=1,vlg(i)
c --
c	!	   j = jj + id
c	!	if(iteration.gt.0) then
		j=vlg_vhcID(i,id)

C	if(j.eq.42)
C     + 	print *, 'Alex001',VhcAtt_Value(42,12,1)

c	!	else
c	!		j = jj + id
c	!	endif
c	print *, 'Alex326c-here='
       	call mtqj_insert(i,j)
	    ntryq(i)=ntryq(i)+1 ! ntryq is the counter to keep tracking number of vehicles in the entry queu
c --
c	print *,'Alexload01',ntryq(i)
c --
c	! assign vehicle attributes
           if(realdm.eq.1.and.iteration.eq.0)then
c --
c	print *, 'Alex11130'
c --
	       call vehicle_generation(t,i,j)
c	print *, 'Alex11131'
c --
c	!           call DYNA_random_number(r2,9)
c	!           if(r2.le.total_hov) then
c	!             ioc(j)=2
c	!           else
c	!             ioc(j)=1
c	!           endif
           endif
c	print *, 'Alex11132'
		jdest(j)=IntDestZone(j,DestVisit(j)) ! initialize jdest(j) regardless iteration
c	print *, 'Alex111321'
           if(iteration.eq.0.or.(iteration.gt.0.and.
     +     vehclass(j).eq.4))then ! when iteration>0, only class 4 will get new path, c	class 1 and 5 will keep using orignal ones
c	print *, 'Alex111322'
              if(realdm.eq.1.or.realdm.eq.0)then
c	print *, 'Alex111323'
		call hot_lane_choice(j)
c	print *, 'Alex324-here=',VhcAtt_Array(j)%PSize,j,i,ipinit
              	call get_veh_path(j,i,ipinit,1) ! pass 1 to select the best path
c	print *, 'Alex325-here=',VhcAtt_Array(j)%PSize
              endif
c	print *, 'Alex11133'
c	! -- if with incident, check if the vehicle's path contains incidents
c	! -- check if the vehicle has incident link on its path before diversion
c	! -- used to calculate impacted vehicle statistics
	      if(inci_num.gt.0)then
	        do MA=1,inci_num
	          jflag=0
		  icnt=0
		  inode1=nint(VhcAtt_Value(j,icnt+1,1))
		  inode2=nint(VhcAtt_Value(j,icnt+2,1))
		  Nlnk=GetFLinkFromNode(inode1,inode2)
c --
C	print *, 'Alex11134'
	do while(idnod(Nlnk).ne.destination(MasterDest(jdest(j))))
	        icnt=icnt+1 
		inode1=nint(VhcAtt_Value(j,icnt+1,1))
		inode2=nint(VhcAtt_Value(j,icnt+2,1))
	        Nlnk=GetFLinkFromNode(inode1,inode2)
                if(Nlnk.eq.incil(MA))then ! still on incident link
c --
! intialize all impacted vehicls to be diverted
! ImpactType(j)%InciMode = 1
                ImpactType(j)%InciMode=2
		ImpactType(J)%InciIM=MA
		jflag=1
		go to 800
                 endif
	          enddo
	        enddo
	      endif
800  	continue
c	print *, 'Alex11140'
c	! some check for work zone
	      if(WorkZoneNum.gt.0)then
	        do MA=1,inci_num
	        jflag=0
		icnt=0
		inode1=nint(VhcAtt_Value(j,icnt+1,1))
		inode2=nint(VhcAtt_Value(j,icnt+2,1))
		Nlnk=GetFLinkFromNode(inode1,inode2)
          do while(idnod(Nlnk).ne.destination(MasterDest(jdest(j))))
	        icnt=icnt+1 
		inode1=nint(VhcAtt_Value(j,icnt+1,1))
		inode2=nint(VhcAtt_Value(j,icnt+2,1))
	        Nlnk=GetFLinkFromNode(inode1,inode2)
                if(Nlnk.eq.incil(MA))then ! still on incident link
	             			! intialize all impacted vehicls to be diverted
					! ImpactType(j)%WZMode = 1
                ImpactType(j)%WZMode=2
		ImpactType(J)%WZIM=MA
		jflag=1
		go to 900
                 endif
	  enddo
	        enddo
	      endif
c --
900       continue
c --
c	print *, 'Alex326-here=',VhcAtt_Array(j)%PSize
c --
          elseif(iteration.gt.0)then
             if(ioc(j).eq.1)then
	          if(vehclass(j).eq.3)then
                     call get_uepath_lov(j,i,icurrnt(j),t) 
	          elseif(vehclass(j).eq.2)then
	             call get_sopath_lov(j,i,icurrnt(j),t)
	          endif
             else
	          if(vehclass(j).eq.3)then
                     call get_uepath_hov(j,i,icurrnt(j),t)
	          elseif(vehclass(j).eq.2)then
	             call get_sopath_hov(j,i,icurrnt(j),t)
	          endif
            endif
          endif
C	print *, 'Alex326b-here=',VhcAtt_Array(j)%PSize
     	enddo
c --
c	print *, 'Alex327-here=',VhcAtt_Array(j)%PSize
!	 jj = jj + vlg(i)
   	endif
c	print *, 'Alex11160'
c --
c	! Load from those finished the activity at the intermediate destinations
c	! if this vehicle will be loaded in this time interval
c	! update RemainDwell, PastDwell
c	! Remove it from the TripChainList
c	! Insert it to the front of the entry queue so that it will be loaded first

c	print *, 'Alex328-here='
   	pass=>TripChainList(i)
c	print *, 'Alex329-here='

   	if(pass%veh.gt.0)then
c		print *, 'Alex11161'
      	do while(associated(pass%next_veh))
         j=pass%veh
c --
         if(RemainDwell(j).LT.tii)then 
            RemainDwell(j)=0
            DestVisit(j)=DestVisit(j)+1
            jdest(j)=IntDestZone(j,DestVisit(j))
            p_TripChain_remove=>pass
c		print *, 'Alex11162'
		call TripChain_remove(i,j) ! Remove j from TripChainList
c		print *, 'Alex11163'
		call mtqj_InsFront(i,j)
c		print *, 'Alex11164'
		ntryq(i)=ntryq(i)+1
		xpar(j)=0.0
c	! get a path for this vehicle
	if(iteration.eq.0.or.(iteration.gt.0.and.vehclass(j).eq.4))then
              if(realdm.eq.1.or.realdm.eq.0)then
c		print *, 'Alex11165'
                 call hot_lane_choice(j)
c		print *, 'Alex11166'
                 call get_veh_path(j,i,ipinit,icurrnt(j)) ! pass 1 to select the best path
              endif
c --
c	! -- if with incident, check if the vehicle's path contains incidents
c	! -- check if the vehicle has incident link on its path before diversion
c	! -- used to calculate impacted vehicle statistics
	    if(inci_num.gt.0)then
c		print *, 'Alex11167'
	    do MA=1,inci_num
	        jflag=0
		icnt=0
		inode1=nint(VhcAtt_Value(j,icnt+1,1))
		inode2=nint(VhcAtt_Value(j,icnt+2,1))
		Nlnk=GetFLinkFromNode(inode1,inode2)
c		print *, 'Alex11168'
          do while(idnod(Nlnk).ne.destination(MasterDest(jdest(j))))
	        icnt=icnt+1 
		inode1=nint(VhcAtt_Value(j,icnt+1,1))
		inode2=nint(VhcAtt_Value(j,icnt+2,1))
	        Nlnk=GetFLinkFromNode(inode1,inode2)
                 if(Nlnk.eq.incil(MA))then ! still on incident link
	                ImpactType(j)%InciMode=1
			ImpactType(J)%InciIM=MA
			jflag=1
		        goto 1000
                 endif
		 enddo
c		print *, 'Alex11169'
	     enddo
c		print *, 'Alex111690'
	     endif
c --
1000      continue
c --
c	print *, 'Alex329-here=',VhcAtt_Array(j)%PSize
c --
            elseif(iteration.gt.0)then
              if(ioc(j).eq.1)then
	             if(vehclass(j).eq.3)then
                    call get_uepath_lov(j,i,icurrnt(j),t) 
	             elseif(vehclass(j).eq.2)then
	                call get_sopath_lov(j,i,icurrnt(j),t)
	             endif
              else
	             if(vehclass(j).eq.3)then
                    call get_uepath_hov(j,i,icurrnt(j),t)
	             elseif(vehclass(j).eq.2)then
	                call get_sopath_hov(j,i,icurrnt(j),t)
	             endif
              endif
            endif
         else
            RemainDwell(j)=RemainDwell(j)-tii
         endif
		 if(associated(pass%next_veh))then
		   pass=>pass%next_veh
		 endif
	  enddo
   	endif
c --
c	print *, 'Alex330-here=',VhcAtt_Array(j)%PSize
c --
c	! Start Loading Vehicles
c	! Check # of vehicles allowed to be loaded
c	!   genm=max(0.0,(maxden*xl(i))-partotal(i))
   	genm=max(0.0,(maxden*xl(i))-npar(i))
c --
c	!*********************************************
c	!link type 9: HOT / freeway
c	!link type 10: HOV / freeway
c	!   if(link_iden(i).ne.1) then
   	if(link_iden(i).ne.1.and.link_iden(i).ne.9.
     +	and.link_iden(i).ne.10)then
c --
c	!*********************************************
c --
     	limentr=max(0,nint((1-(partotal(i)/(maxden*xl(i))))
     +   *entrymx*nlanes(i)*tii/60.0))
c	!    limentr=max(0,nint((1-(npar(i)/(maxden*xl(i))))*entrymx*nlanes(i)*tii/60.0))
     	mnum=nint(min(genm,float(ntryq(i)),float(limentr)))
   	else ! loading on freeway (external loading should not be constrained as above)
c	!    limentr=max(0,nint(entrymx*nlanes(i)*tii/60.0))
c	!     slimentr=MaxFlowRate(i)/tii 
c --
	slimentr=MaxFlowRate(i)*tii*60.0
c --
     	mnum=nint(min(genm,float(ntryq(i)),slimentr))
   	endif
c --
   	if(mnum.lt.0)then
      	write(911,'("Error, oversaturation on generation 
     +   link",i7,"->",i7)') nodenum(idnod(i)),nodenum(iunod(i))
      	stop
   	endif
   	link_entry_time(i)=0
c --
C	print *, 'Alex11190'
c	!-----------------------------------------------
c	! Start loading vehicles from the entry queue
C	print *, 'Alex331-here=',VhcAtt_Array(j)%PSize
   	if(mnum.gt.0)then
     	entry_service(i,inentry(i))=float(mnum)
     	do ii=1,mnum
        p_mtqj_value=>EntQueVehList(i)
        if(p_mtqj_value%veh.lt.0)then
	      print *, 'error in loading from entry queue'
        endif
	    j1=mtqj_value(i)
	    if(j1.lt.1)print *, 'error in finding j1'
c --
        if(partotal(i)+mtnum(j1).gt.maxden*xl(i)) exit ! if the link could not accommodate this additional vehicle, quit the loop
!        if(npar(i).gt.maxden*xl(i)) exit ! if the link could not accommodate this additional vehicle, quit the loop
c --
        call mtxj_insert(i,j1) !LST
        npar(i)=npar(i)+1
        if(vehclass2(j1).eq.2.or.vehclass2(j1).eq.5.or.
     +  vehclass2(j1).eq.7) nTruck(i)=nTruck(i)+1
c --
		volume(i)=volume(i)+1
        partotal(i)=partotal(i)+mtnum(j1)

	    call mtqj_remove(i,j1)
        ntryq(i)=ntryq(i)-1
        link_entry_time(i)=link_entry_time(i)+(t-stime(j1))
     	enddo
	 link_entry_time(i)=link_entry_time(i)/mnum     
   	else
     	if(ntryq(i).eq.0)then
	entry_service(i,inentry(i))=limentr
	link_entry_time(i)=0
	else
	entry_service(i,inentry(i))=0
	link_entry_time(i)=10
	endif 
   	endif
C	print *, 'Alex100'
c	! --
c	! --Averaging of the entry_service() for nu_de simulation intervals.
c	! --Keep the average entry_service() in entryrate().
c	! --
C	print *, 'Alex332-here=',VhcAtt_Array(j)%PSize
   	inentry(i)=inentry(i)+1
   	if(inentry(i).eq.nu_de+1) inentry(i)=1
   	entryrate(i)=0
   	do kk=1,nu_de
      	entryrate(i)=entryrate(i)+entry_service(i,kk)
   	enddo
   	entryrate(i)=entryrate(i)/nu_de
C	print *, 'Alex333-here=',VhcAtt_Array(j)%PSize
   	if(nubus.gt.0)then
     	if(iteration.eq.0)then
        if(TotalBusGen.lt.nubus) call bus_generation(i,t)
     	endif
   	endif
	end if ! screen for link_iden
c	print *, 'Alex334-here=',VhcAtt_Array(j)%PSize,j
7 	continue
c	print *, 'Alex335-here=',VhcAtt_Array(j)%PSize

	if(associated(pass%next_veh)) deallocate(pass)
C	print *, 'Alex111110'
      return
      end
