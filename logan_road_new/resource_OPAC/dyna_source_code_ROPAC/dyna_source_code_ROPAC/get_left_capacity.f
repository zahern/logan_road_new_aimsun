      subroutine get_left_capacity(ilink,oppomode)       
c --
c -- This subroutine calculates the left turning capacity for link "ilink"
c --
c -- This subroutine is called from get_link_capacity      
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT : 
c --  ilink : the current link, for which the left turn capacity is calculated.
c --
c -- OUTPUT :
c --         left turn capacity for link "ilink" in unit of vphpl
c --
      use muc_mod 
c --
      integer oppomode
c --
c -- reset all the value to the array index
c -- gcratio 0.3,0.4,0.5,0.6,0.7 =>1,2,3,4,5
c -- opp_lane ==> 1,2,3 (number of lanes for the opposing link)
c -- opp_volume ==> 200,300,400,500,600,800,1000 (on the opposing link)
c --                  1,  2,  3,  4,  5,  6,   7
c -- volume ==> 100,200,300,400,500,600,700 (on the current link)
c -- range i => 1 -- 5 : gcratio
c --       j => 1 - 3  : opp_lanes
c --       k => 1 - 7  : current traffic volume
c --       l => 1- 7   : opp_volume
c --
c -- NOTE : this subroutine uses the data provided in leftcap.dat (fort.48)
c --
c -- Convert the gcratio for the current link into the corresponding index
c --

	if(ilink.eq.336.and.iteration.eq.1)then
		iiidebug=1
	endif


      if(oppomode.lt.1)then									! no opposing traffic in the same phase (protected)
		left_capacity(ilink)=SatFlowRate(ilink)/nlanes(ilink)
	else

      do ii=1,5
          if(gcratio(ilink).gt.(0.2+0.1*ii).and.
     +      gcratio(ilink).le.(0.3+0.1*ii) ) i=ii 
      enddo
      if(gcratio(ilink).le.0.3) i=1
      if(gcratio(ilink).gt.0.8) i=5
c --
c -- the index j = number of lanes for the opposing link.
c --
c -- NOTE : the maximum number of lanes for the opposing link, in the input file
c --        is 3.  Therefore, if j> 3 set j=3
c --
      j=opp_lane(ilink)

      if(j.gt.3) j=3
c --
c -- Convert the volume on the current link into the corresponding index.
c --
c -- volk : is the volume on the link (vehicle/hr/lane) in hundreds.
c --        (for example if the volume is 500 then volk=5)
c --
      volk1=c(ilink)*v(ilink)*60
      volk=(volk1/(nlanes(ilink)*100))
      k=ifix(volk)

      if(k.lt.1) k=1
      if(k.gt.7) k=7
c --
c -- Convert the volume on the opposing link into the corresponding index.
c --
c -- NOTE : the numbers 3,6,8,10 correspond to volumes
c --        300,600, 800, 1000 in the input file.
c -- 
      l_o=nint(c(opp_linkS(ilink))*v(opp_linkS(ilink))*60/
     *        (100*nlanes(opp_linkS(ilink))))

	Select Case (l_o)
      Case (:2) 
	  l_o=1
      Case (3:5) 
	  l_o=l_o-1
      Case (6:7) 
	  l_o=5
      Case (8:9) 
	  l_o=6
      Case (10:) 
	  l_o=7
	End Select
c --
!      if(bay(ilink)) then

      if(bay(ilink).ge.1)then
         !left_capacity(ilink)=float(leftcapWb(i,j,l_o))/3600.0

	left_capacity(ilink)=float(leftcapWb(i,j,l_o))*bay(ilink)/3600.0 
      else
      left_capacity(ilink)=float(leftcapWOb(i,j,k,l_o))/3600.0
      endif
c --
c	if(ilink.eq.100)then
c	print *,oppomode,i,j,k,l_o
c	pause
c     endif

c --         
      if(gcratio(ilink).gt.0)then
		left_capacity(ilink)=left_capacity(ilink)/gcratio(ilink)
      endif

      endif


c	if(ilink.eq.100)then
c	print *,left_capacity(ilink),oppomode
c	pause
c     endif

      end subroutine
